// web/src/pages/Report.tsx
import { useEffect, useRef, useState } from "react"
import { useParams, useNavigate } from "react-router-dom"
import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"
import { api, openProgressStream } from "../api/client"
import type { Analysis, ProgressEvent } from "../types"
import ProgressTimeline from "../components/ProgressTimeline"
import ReportBanner from "../components/ReportBanner"
import ReportTabs from "../components/ReportTabs"

// ── Analyst section definitions ───────────────────────────────────────────────
const ANALYST_SECTIONS = [
  { field: "fundamentals_report",    label: "📊 基本面分析", analyst: "fundamentals" },
  { field: "sentiment_report",       label: "💬 情绪分析",   analyst: "sentiment" },
  { field: "news_report",            label: "📰 新闻分析",   analyst: "news" },
  { field: "market_report",          label: "📈 技术分析",   analyst: "market" },
  { field: "investment_plan",        label: "🧠 投研总结",   analyst: null },
  { field: "trader_investment_plan", label: "💼 交易建议",   analyst: null },
]

// ── Live section card (shown while analysis is running) ───────────────────────
function LiveSection({
  label,
  content,
  isPending,
}: {
  label: string
  content: string | null | undefined
  isPending: boolean
}) {
  const [expanded, setExpanded] = useState(true)

  if (isPending) {
    return (
      <div className="border border-border rounded-lg overflow-hidden opacity-50">
        <div className="px-4 py-3 bg-surface flex items-center gap-2 text-gray-500 text-sm">
          <span className="w-1.5 h-1.5 rounded-full bg-border" />
          {label}
          <span className="ml-auto text-xs">等待中…</span>
        </div>
      </div>
    )
  }

  if (!content) {
    return (
      <div className="border border-accent/30 rounded-lg overflow-hidden">
        <div className="px-4 py-3 bg-surface flex items-center gap-2 text-accent text-sm">
          <span className="w-1.5 h-1.5 rounded-full bg-accent animate-pulse" />
          {label}
          <span className="ml-auto text-xs animate-pulse">生成中…</span>
        </div>
      </div>
    )
  }

  return (
    <div className="border border-buy/30 rounded-lg overflow-hidden">
      <button
        onClick={() => setExpanded((v) => !v)}
        className="w-full px-4 py-3 bg-surface flex items-center gap-2 text-white text-sm text-left hover:bg-surface/80 transition-colors"
      >
        <span className="text-buy">✓</span>
        {label}
        <span className="ml-auto text-gray-500 text-xs">{expanded ? "▲ 收起" : "▼ 展开"}</span>
      </button>
      {expanded && (
        <div className="px-5 py-4 border-t border-border bg-bg/50 report-content text-sm max-h-96 overflow-y-auto">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
        </div>
      )}
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

      // Open SSE stream
      const es = openProgressStream(
        id,
        (event) => {
          setProgress(event)
          // Re-fetch full analysis data whenever SSE says to refresh
          if ((event as any).refresh) {
            api.getAnalysis(id).then(setAnalysis)
          }
        },
        () => {
          // Stream closed — do a final fetch to get complete result
          api.getAnalysis(id).then(setAnalysis)
        }
      )
      esRef.current = es
    })
    return () => esRef.current?.close()
  }, [id])

  if (loading) return <div className="p-10 text-gray-400">加载中…</div>
  if (!analysis) return <div className="p-10 text-red-400">未找到该分析</div>

  const displayStatus = progress?.status ?? analysis.status
  const displayStage  = progress?.stage  ?? analysis.stage
  const displayDetail = progress?.detail ?? analysis.stage_detail

  // ── Analysis failed ────────────────────────────────────────────────────────
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

  // ── Analysis running — show timeline + live partial results ────────────────
  if (displayStatus === "running" || displayStatus === "pending") {
    const result = analysis.result ?? {}

    // Which analysts were selected for this run
    const selectedAnalysts = analysis.analysts ?? []

    // Determine section state: done / active / pending
    const activeSectionIdx = ANALYST_SECTIONS.findIndex(
      (s) => !result[s.field as keyof typeof result] &&
             (s.analyst === null || selectedAnalysts.includes(s.analyst))
    )

    return (
      <div className="max-w-3xl mx-auto px-4 py-6">
        {/* Compact progress header */}
        <div className="bg-surface border border-border rounded-lg p-4 mb-6">
          <div className="flex items-start justify-between mb-3">
            <div>
              <span className="text-white font-semibold">{analysis.ticker}</span>
              <span className="text-gray-400 text-sm ml-2">{analysis.trade_date}</span>
            </div>
            <span className="text-xs text-accent bg-accent/10 border border-accent/30 rounded px-2 py-0.5 animate-pulse">
              分析中
            </span>
          </div>
          <ProgressTimeline stage={displayStage} status={displayStatus} detail={displayDetail} />
        </div>

        {/* Live partial results */}
        <div className="space-y-3">
          <h2 className="text-gray-400 text-xs uppercase tracking-wide mb-2">分析过程（实时）</h2>
          {ANALYST_SECTIONS.map((s, idx) => {
            // Skip if analyst not selected
            if (s.analyst && !selectedAnalysts.includes(s.analyst)) return null

            const content = result[s.field as keyof typeof result] as string | null
            const isActive  = idx === activeSectionIdx && !content
            const isPending = idx > activeSectionIdx && !content

            return (
              <LiveSection
                key={s.field}
                label={s.label}
                content={content}
                isPending={isPending && !isActive}
              />
            )
          })}
        </div>
      </div>
    )
  }

  // ── Analysis complete ──────────────────────────────────────────────────────
  if (!analysis.result || !analysis.decision) {
    return <div className="p-10 text-gray-400">报告数据缺失</div>
  }

  return (
    <div>
      <ReportBanner
        ticker={analysis.ticker}
        tickerName={analysis.ticker_name}
        tradeDate={analysis.trade_date}
        decision={analysis.decision}
        depth={analysis.depth}
        analystCount={analysis.analysts.length}
      />
      <ReportTabs result={analysis.result} analysts={analysis.analysts} />
    </div>
  )
}
