// web/src/components/ProgressTimeline.tsx
import { useEffect, useState } from "react"

const STAGES = [
  { key: "analysts", label: "分析师团队", sub: "基本面 · 情绪 · 新闻 · 技术" },
  { key: "debate",   label: "多空辩论",   sub: "多方 vs 空方研究员" },
  { key: "risk",     label: "风险评估",   sub: "激进 · 中性 · 保守分析师" },
  { key: "decision", label: "最终决策",   sub: "组合经理综合判断" },
]

const ORDER = ["analysts", "debate", "risk", "decision", "complete"]

function stageIndex(stage: string) {
  const idx = ORDER.indexOf(stage)
  return idx === -1 ? 0 : idx
}

interface Props {
  stage: string
  status: string
  detail?: string | null
}

export default function ProgressTimeline({ stage, status, detail }: Props) {
  // Elapsed time counter
  const [elapsed, setElapsed] = useState(0)
  useEffect(() => {
    if (status !== "running" && status !== "pending") return
    const t = setInterval(() => setElapsed((s) => s + 1), 1000)
    return () => clearInterval(t)
  }, [status])

  const elapsedStr = elapsed > 0
    ? elapsed >= 60
      ? `${Math.floor(elapsed / 60)}分${elapsed % 60}秒`
      : `${elapsed}秒`
    : null

  return (
    <div className="max-w-lg mx-auto py-12 px-6">
      {/* Header */}
      <div className="text-center mb-10">
        <div className="text-4xl mb-3">📊</div>
        <h2 className="text-xl font-bold text-white">分析进行中</h2>
        <p className="text-gray-400 text-sm mt-1">
          完成后可离开此页，稍后回来查看
          {elapsedStr && <span className="ml-2 text-gray-500">已运行 {elapsedStr}</span>}
        </p>
      </div>

      {/* Timeline */}
      <div className="space-y-0 mb-8">
        {STAGES.map((s, i) => {
          const currentIdx = stageIndex(stage)
          const done = currentIdx > i || status === "complete"
          const active = stageIndex(stage) === i && status === "running"

          return (
            <div key={s.key} className="flex gap-4">
              <div className="flex flex-col items-center">
                <div className={`w-3 h-3 rounded-full mt-1 shrink-0 transition-colors ${
                  done   ? "bg-buy" :
                  active ? "bg-accent animate-pulse" :
                           "bg-border"
                }`} />
                {i < STAGES.length - 1 && (
                  <div className={`w-px flex-1 my-1 ${done ? "bg-buy/40" : "bg-border"}`} />
                )}
              </div>
              <div className={`pb-6 ${done || active ? "text-white" : "text-gray-500"}`}>
                <div className="font-medium text-sm flex items-center gap-2">
                  {s.label}
                  {done && <span className="text-buy text-xs">✓</span>}
                  {active && <span className="text-accent text-xs animate-pulse">进行中</span>}
                </div>
                <div className="text-xs opacity-60">{s.sub}</div>
              </div>
            </div>
          )
        })}
      </div>

      {/* Current activity detail */}
      {detail && status === "running" && (
        <div className="bg-surface border border-border rounded-lg px-4 py-3 text-sm">
          <div className="text-gray-500 text-xs mb-1">当前进展</div>
          <div className="text-gray-200 flex items-center gap-2">
            <span className="inline-block w-1.5 h-1.5 bg-accent rounded-full animate-pulse shrink-0" />
            {detail}
          </div>
        </div>
      )}

      {status === "failed" && (
        <p className="text-red-400 text-center text-sm mt-4">
          分析失败，请检查日志或重新提交
        </p>
      )}
    </div>
  )
}
