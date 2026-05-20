// web/src/pages/History.tsx
import { useEffect, useState } from "react"
import { useNavigate } from "react-router-dom"
import { api } from "../api/client"
import type { Analysis } from "../types"

const DECISION_COLOR: Record<string, string> = {
  BUY: "text-buy border-buy bg-buy/10",
  SELL: "text-sell border-sell bg-sell/10",
  HOLD: "text-hold border-hold bg-hold/10",
}

const STATUS_LABEL: Record<string, string> = {
  pending: "等待中",
  running: "分析中…",
  complete: "完成",
  failed: "失败",
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

  if (loading) return <div className="p-10 text-gray-400">加载中…</div>

  if (analyses.length === 0)
    return (
      <div className="p-10 text-center text-gray-400">
        <p className="text-lg mb-2">暂无分析记录</p>
        <button
          onClick={() => navigate("/new")}
          className="text-accent hover:underline text-sm"
        >
          新建第一个分析 →
        </button>
      </div>
    )

  return (
    <div className="px-6 py-8 max-w-3xl mx-auto">
      <h1 className="text-2xl font-bold text-white mb-6">历史报告</h1>
      <div className="space-y-3">
        {analyses.map((a) => (
          <div
            key={a.id}
            onClick={() => navigate(`/report/${a.id}`)}
            className="bg-surface border border-border rounded-lg p-4 cursor-pointer hover:border-accent/50 transition-colors flex items-center justify-between"
          >
            <div>
              <div className="flex items-center gap-2">
                <span className="font-semibold text-white">{a.ticker}</span>
                {a.ticker_name && (
                  <span className="text-sm text-gray-400">{a.ticker_name}</span>
                )}
                {!a.seen && <span className="w-2 h-2 bg-accent rounded-full" />}
              </div>
              <div className="text-sm text-gray-400 mt-0.5">
                {a.trade_date} · 深度 {a.depth} · {a.analysts.length} 位分析师
              </div>
            </div>
            <div className="text-right shrink-0">
              {a.decision ? (
                <span
                  className={`inline-block px-2 py-0.5 rounded border text-sm font-bold ${
                    DECISION_COLOR[a.decision] ?? "text-gray-400"
                  }`}
                >
                  {a.decision}
                </span>
              ) : (
                <span className="text-sm text-gray-500">
                  {STATUS_LABEL[a.status] ?? a.status}
                </span>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
