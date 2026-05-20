// web/src/pages/Report.tsx
import { useEffect, useState } from "react"
import { useParams, useNavigate } from "react-router-dom"
import { api, openProgressStream } from "../api/client"
import type { Analysis, ProgressEvent } from "../types"
import ProgressTimeline from "../components/ProgressTimeline"
import ReportBanner from "../components/ReportBanner"
import ReportTabs from "../components/ReportTabs"

export default function Report() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const [analysis, setAnalysis] = useState<Analysis | null>(null)
  const [progress, setProgress] = useState<ProgressEvent | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    if (!id) return
    api.getAnalysis(id).then((a) => {
      setAnalysis(a)
      setLoading(false)

      if (a.status === "complete" || a.status === "failed") return

      const es = openProgressStream(
        id,
        (event) => setProgress(event),
        () => api.getAnalysis(id).then(setAnalysis)
      )
      return () => es.close()
    })
  }, [id])

  if (loading) return <div className="p-10 text-gray-400">加载中…</div>
  if (!analysis) return <div className="p-10 text-red-400">未找到该分析</div>

  const displayStatus = progress?.status ?? analysis.status
  const displayStage = progress?.stage ?? analysis.stage

  if (displayStatus === "running" || displayStatus === "pending") {
    return <ProgressTimeline stage={displayStage} status={displayStatus} />
  }

  if (displayStatus === "failed") {
    return (
      <div className="p-10 text-center">
        <p className="text-red-400 text-lg mb-2">分析失败</p>
        <p className="text-gray-400 text-sm mb-4">{analysis.error ?? "未知错误"}</p>
        <button
          onClick={() => navigate("/new")}
          className="text-accent hover:underline text-sm"
        >
          重新分析 →
        </button>
      </div>
    )
  }

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
