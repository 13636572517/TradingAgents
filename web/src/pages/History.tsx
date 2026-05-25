// web/src/pages/History.tsx
import { useEffect, useState } from "react"
import { useNavigate } from "react-router-dom"
import { api } from "../api/client"
import type { Analysis } from "../types"

const DECISION_STYLE: Record<string, string> = {
  BUY:  "text-buy  border-buy/50  bg-buy/10",
  SELL: "text-sell border-sell/50 bg-sell/10",
  HOLD: "text-hold border-hold/50 bg-hold/10",
}

const STATUS_LABEL: Record<string, { label: string; cls: string }> = {
  pending:  { label: "等待中",  cls: "text-gray-400" },
  running:  { label: "分析中…", cls: "text-accent animate-pulse" },
  complete: { label: "完成",    cls: "text-buy" },
  failed:   { label: "失败",    cls: "text-red-400" },
  stopped:  { label: "已停止",  cls: "text-hold" },
}

function AnalysisCard({
  analysis,
  onDelete,
}: {
  analysis: Analysis
  onDelete: (id: string) => void
}) {
  const navigate = useNavigate()
  const [confirming, setConfirming] = useState(false)
  const [deleting, setDeleting] = useState(false)

  const handleDelete = async (e: React.MouseEvent) => {
    e.stopPropagation()
    if (!confirming) {
      setConfirming(true)
      setTimeout(() => setConfirming(false), 3000) // auto-cancel after 3s
      return
    }
    setDeleting(true)
    try {
      await api.deleteAnalysis(analysis.id)
      onDelete(analysis.id)
    } catch {
      setDeleting(false)
      setConfirming(false)
    }
  }

  const statusInfo = STATUS_LABEL[analysis.status] ?? { label: analysis.status, cls: "text-gray-400" }

  return (
    <div
      onClick={() => navigate(`/report/${analysis.id}`)}
      className="bg-surface border border-border rounded-xl p-4 cursor-pointer hover:border-accent/40 transition-colors group relative flex flex-col gap-3"
    >
      {/* Delete button */}
      <button
        onClick={handleDelete}
        disabled={deleting}
        className={`absolute top-3 right-3 text-xs px-2 py-0.5 rounded transition-colors opacity-0 group-hover:opacity-100 ${
          confirming
            ? "bg-red-500/20 text-red-400 border border-red-500/40 opacity-100"
            : "text-gray-500 hover:text-red-400 hover:bg-red-500/10"
        }`}
        title={confirming ? "再次点击确认删除" : "删除"}
      >
        {deleting ? "删除中" : confirming ? "确认删除？" : "✕"}
      </button>

      {/* Header */}
      <div className="flex items-start justify-between pr-8">
        <div>
          <div className="flex items-center gap-2">
            <span className="font-semibold text-white text-base">{analysis.ticker}</span>
            {!analysis.seen && (
              <span className="w-1.5 h-1.5 bg-accent rounded-full" />
            )}
          </div>
          {analysis.ticker_name && (
            <div className="text-xs text-gray-400 mt-0.5 truncate max-w-[200px]">{analysis.ticker_name}</div>
          )}
        </div>
        {analysis.decision ? (
          <span className={`text-sm font-bold px-2 py-0.5 rounded border ${DECISION_STYLE[analysis.decision] ?? "text-gray-400"}`}>
            {analysis.decision}
          </span>
        ) : (
          <span className={`text-xs ${statusInfo.cls}`}>{statusInfo.label}</span>
        )}
      </div>

      {/* Meta */}
      <div className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-gray-500">
        <span>📅 {analysis.trade_date}</span>
        <span>🔍 深度 {analysis.depth}</span>
        <span>👥 {analysis.analysts.length} 位分析师</span>
      </div>

      {/* Analyst tags */}
      <div className="flex flex-wrap gap-1">
        {analysis.analysts.map((a) => (
          <span key={a} className="text-xs bg-bg border border-border rounded px-1.5 py-0.5 text-gray-400">
            {a === "fundamentals"               ? "基本面" :
             (a === "sentiment" || a === "social") ? "情绪"   :
             a === "news"                       ? "新闻"   :
             a === "market"                     ? "技术"   : a}
          </span>
        ))}
      </div>

      {/* Footer: time + tokens */}
      <div className="flex items-center justify-between">
        <span className="text-xs text-gray-600">
          {new Date(analysis.created_at).toLocaleString("zh-CN", {
            month: "numeric", day: "numeric",
            hour: "2-digit", minute: "2-digit",
          })}
        </span>
        {analysis.usage && (
          <span className="text-xs font-mono text-gray-400 bg-bg border border-border rounded px-1.5 py-0.5">
            {(() => {
              const total = (
                analysis.usage.quick.tokens_in + analysis.usage.quick.tokens_out +
                analysis.usage.deep.tokens_in  + analysis.usage.deep.tokens_out
              )
              return total > 0 ? `${total.toLocaleString()} tokens` : ""
            })()}
          </span>
        )}
      </div>
    </div>
  )
}

export default function History() {
  const navigate = useNavigate()
  const [analyses, setAnalyses] = useState<Analysis[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api.listAnalyses().then((r) => {
      setAnalyses(r.items)
      setLoading(false)
    })
  }, [])

  const handleDelete = (id: string) => {
    setAnalyses((prev) => prev.filter((a) => a.id !== id))
  }

  if (loading) return <div className="p-10 text-gray-400">加载中…</div>

  if (analyses.length === 0) {
    return (
      <div className="p-10 text-center text-gray-400">
        <p className="text-lg mb-2">暂无分析记录</p>
        <button onClick={() => navigate("/new")} className="text-accent hover:underline text-sm">
          新建第一个分析 →
        </button>
      </div>
    )
  }

  return (
    <div className="px-6 py-8">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold text-white">历史报告</h1>
        <span className="text-gray-500 text-sm">{analyses.length} 条记录</span>
      </div>

      {/* Grid layout: 1 col mobile / 2 col md / 3 col xl */}
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
        {analyses.map((a) => (
          <AnalysisCard key={a.id} analysis={a} onDelete={handleDelete} />
        ))}
      </div>
    </div>
  )
}
