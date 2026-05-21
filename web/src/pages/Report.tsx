// web/src/pages/Report.tsx
import { useEffect, useRef, useState } from "react"
import { useParams, useNavigate } from "react-router-dom"
import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"
import { api, openProgressStream } from "../api/client"
import type { Analysis, ProgressEvent } from "../types"


// ── Section tree definition ───────────────────────────────────────────────────
const TREE = [
  {
    group: "分析师团队",
    icon: "🔍",
    items: [
      { key: "fundamentals_report",    label: "基本面分析师", icon: "📊", analyst: "fundamentals" },
      { key: "sentiment_report",       label: "情绪分析师",   icon: "💬", analyst: "sentiment" },
      { key: "news_report",            label: "新闻分析师",   icon: "📰", analyst: "news" },
      { key: "market_report",          label: "技术分析师",   icon: "📈", analyst: "market" },
    ],
  },
  {
    group: "投研决策",
    icon: "🧠",
    items: [
      { key: "investment_plan",         label: "投研总结",   icon: "🧠", analyst: null },
      { key: "trader_investment_plan",  label: "交易建议",   icon: "💼", analyst: null },
      { key: "final_trade_decision",    label: "最终决策",   icon: "📋", analyst: null },
    ],
  },
]

// ── Status icon ───────────────────────────────────────────────────────────────
function StatusDot({ state }: { state: "done" | "active" | "pending" }) {
  if (state === "done")    return <span className="text-buy text-xs">✓</span>
  if (state === "active")  return <span className="w-2 h-2 rounded-full bg-accent animate-pulse inline-block" />
  return <span className="w-2 h-2 rounded-full bg-border inline-block" />
}

// ── Elapsed timer ─────────────────────────────────────────────────────────────
function useElapsed(running: boolean) {
  const [elapsed, setElapsed] = useState(0)
  useEffect(() => {
    if (!running) return
    const t = setInterval(() => setElapsed((s) => s + 1), 1000)
    return () => clearInterval(t)
  }, [running])
  if (elapsed === 0) return ""
  return elapsed >= 60
    ? `${Math.floor(elapsed / 60)}分${elapsed % 60}秒`
    : `${elapsed}秒`
}

// ── Two-panel workspace (running + complete) ──────────────────────────────────
function AnalysisWorkspace({
  analysis,
  progress,
  isRunning,
}: {
  analysis: Analysis
  progress: ProgressEvent | null
  isRunning: boolean
}) {
  const result = analysis.result ?? {}
  const selectedAnalysts = analysis.analysts ?? []
  const elapsed = useElapsed(isRunning)

  // All available items (filtered by selected analysts)
  const allItems = TREE.flatMap((g) =>
    g.items.filter((it) => it.analyst === null || selectedAnalysts.includes(it.analyst))
  )

  // Auto-select first available item
  const firstDone = allItems.find((it) => result[it.key as keyof typeof result])
  const [activeKey, setActiveKey] = useState<string>(() => firstDone?.key ?? allItems[0]?.key ?? "")

  // Update selection when first report arrives
  useEffect(() => {
    if (!activeKey || !result[activeKey as keyof typeof result]) {
      const first = allItems.find((it) => result[it.key as keyof typeof result])
      if (first) setActiveKey(first.key)
    }
  }, [result])

  const displayStage  = progress?.stage  ?? analysis.stage
  const displayDetail = progress?.detail ?? analysis.stage_detail

  const activeContent = result[activeKey as keyof typeof result] as string | null | undefined

  return (
    <div className="flex flex-col h-screen">
      {/* Top status bar */}
      <div className="bg-surface border-b border-border px-4 py-2.5 flex items-center gap-3 shrink-0">
        <span className="font-semibold text-white">{analysis.ticker}</span>
        <span className="text-gray-500 text-sm">{analysis.trade_date}</span>
        {analysis.decision && (
          <span className={`text-xs font-bold px-2 py-0.5 rounded border ${
            analysis.decision === "BUY"  ? "text-buy border-buy/50 bg-buy/10" :
            analysis.decision === "SELL" ? "text-sell border-sell/50 bg-sell/10" :
                                           "text-hold border-hold/50 bg-hold/10"
          }`}>{analysis.decision}</span>
        )}
        {isRunning && (
          <>
            <span className="text-xs text-accent bg-accent/10 border border-accent/30 rounded px-2 py-0.5 animate-pulse ml-1">
              分析中
            </span>
            {elapsed && <span className="text-xs text-gray-500">已运行 {elapsed}</span>}
          </>
        )}
        {isRunning && displayDetail && (
          <span className="text-xs text-gray-400 ml-2 hidden md:block truncate max-w-xs">
            · {displayDetail}
          </span>
        )}
      </div>

      <div className="flex flex-1 overflow-hidden">
        {/* ── Left tree panel ── */}
        <div className="w-52 shrink-0 bg-surface border-r border-border overflow-y-auto py-3">
          {TREE.map((group) => {
            const groupItems = group.items.filter(
              (it) => it.analyst === null || selectedAnalysts.includes(it.analyst)
            )
            if (groupItems.length === 0) return null
            return (
              <div key={group.group} className="mb-4">
                <div className="px-3 pb-1 text-xs text-gray-500 uppercase tracking-wide flex items-center gap-1">
                  <span>{group.icon}</span> {group.group}
                </div>
                {groupItems.map((item) => {
                  const content = result[item.key as keyof typeof result]
                  const hasContent = !!content

                  // Find which item is "active" (generating right now)
                  const firstEmpty = groupItems.find(
                    (it) => !result[it.key as keyof typeof result]
                  )
                  const isGenerating = isRunning && !hasContent && item.key === firstEmpty?.key

                  const state: "done" | "active" | "pending" = hasContent
                    ? "done"
                    : isGenerating
                    ? "active"
                    : "pending"

                  return (
                    <button
                      key={item.key}
                      onClick={() => hasContent && setActiveKey(item.key)}
                      disabled={!hasContent}
                      className={`w-full text-left px-3 py-2 flex items-center gap-2 text-sm transition-colors ${
                        activeKey === item.key && hasContent
                          ? "bg-accent/15 text-white border-r-2 border-accent"
                          : hasContent
                          ? "hover:bg-white/5 text-gray-300"
                          : "text-gray-600 cursor-default"
                      }`}
                    >
                      <StatusDot state={state} />
                      <span>{item.icon}</span>
                      <span className="truncate">{item.label}</span>
                    </button>
                  )
                })}
              </div>
            )
          })}

          {/* Usage card (shown when complete) */}
          {!isRunning && analysis.usage && (
            <div className="border-t border-border pt-3 px-3 pb-2">
              <div className="text-xs text-gray-500 mb-2">本次用量</div>
              <div className="space-y-1.5 text-xs">
                {(["quick", "deep"] as const).map((role) => {
                  const s = analysis.usage![role]
                  return (
                    <div key={role} className="flex justify-between text-gray-400">
                      <span>{role === "quick" ? "快速" : "深度"} {s.calls}次</span>
                      <span className="text-gray-500 font-mono">
                        {s.cost_cny > 0 ? `¥${s.cost_cny.toFixed(4)}` : "-"}
                      </span>
                    </div>
                  )
                })}
                <div className="flex justify-between text-white border-t border-border pt-1">
                  <span>合计</span>
                  <span className="font-mono">
                    {analysis.usage.total_cost_cny > 0
                      ? `¥${analysis.usage.total_cost_cny.toFixed(4)}`
                      : "-"}
                  </span>
                </div>
              </div>
            </div>
          )}

          {/* Progress timeline mini view */}
          {isRunning && (
            <div className="px-3 mt-2 border-t border-border pt-3">
              <div className="text-xs text-gray-500 mb-2">整体进度</div>
              {["analysts", "debate", "risk", "decision"].map((s, i) => {
                const order = ["analysts", "debate", "risk", "decision", "complete"]
                const currentIdx = order.indexOf(displayStage)
                const done = currentIdx > i
                const active = displayStage === s
                return (
                  <div key={s} className="flex items-center gap-2 mb-1.5">
                    <div className={`w-2 h-2 rounded-full shrink-0 ${
                      done ? "bg-buy" : active ? "bg-accent animate-pulse" : "bg-border"
                    }`} />
                    <span className={`text-xs ${done || active ? "text-gray-300" : "text-gray-600"}`}>
                      {["分析师", "辩论", "风控", "决策"][i]}
                    </span>
                    {done && <span className="text-buy text-xs ml-auto">✓</span>}
                  </div>
                )
              })}
            </div>
          )}
        </div>

        {/* ── Right content panel ── */}
        <div className="flex-1 overflow-y-auto">
          {activeContent ? (
            <div className="p-6 max-w-4xl">
              <div className="report-content">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>{activeContent}</ReactMarkdown>
              </div>
            </div>
          ) : isRunning ? (
            <div className="flex items-center justify-center h-64 text-gray-500">
              <div className="text-center">
                <div className="text-2xl mb-3 animate-pulse">⏳</div>
                <p className="text-sm">等待分析结果…</p>
                {displayDetail && (
                  <p className="text-xs text-gray-600 mt-1">{displayDetail}</p>
                )}
              </div>
            </div>
          ) : (
            <div className="flex items-center justify-center h-64 text-gray-500 text-sm">
              从左侧选择一个分析报告
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

// ── Main Report page ──────────────────────────────────────────────────────────
export default function Report() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const [analysis, setAnalysis] = useState<Analysis | null>(null)
  const [progress, setProgress] = useState<ProgressEvent | null>(null)
  const [loading, setLoading] = useState(true)
  const esRef = useRef<EventSource | null>(null)

  useEffect(() => {
    if (!id) return
    api.getAnalysis(id).then((a) => {
      setAnalysis(a)
      setLoading(false)

      if (a.status === "complete" || a.status === "failed") return

      const es = openProgressStream(
        id,
        (event) => {
          setProgress(event)
          if ((event as any).refresh) {
            api.getAnalysis(id).then(setAnalysis)
          }
        },
        () => api.getAnalysis(id).then(setAnalysis)
      )
      esRef.current = es
    })
    return () => esRef.current?.close()
  }, [id])

  if (loading) return <div className="p-10 text-gray-400">加载中…</div>
  if (!analysis) return <div className="p-10 text-red-400">未找到该分析</div>

  const displayStatus = progress?.status ?? analysis.status

  if (displayStatus === "failed") {
    return (
      <div className="p-10 text-center">
        <p className="text-red-400 text-lg mb-2">分析失败</p>
        <p className="text-gray-400 text-sm mb-4">{analysis.error ?? "未知错误"}</p>
        <button onClick={() => navigate("/new")} className="text-accent hover:underline text-sm">
          重新分析 →
        </button>
      </div>
    )
  }

  const isRunning = displayStatus === "running" || displayStatus === "pending"

  // Unified two-panel view for both running and complete states
  return <AnalysisWorkspace analysis={analysis} progress={progress} isRunning={isRunning} />
}
