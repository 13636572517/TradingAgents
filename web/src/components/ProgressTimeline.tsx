// web/src/components/ProgressTimeline.tsx
const STAGES = [
  { key: "analysts", label: "分析师团队", sub: "基本面 · 情绪 · 新闻 · 技术" },
  { key: "debate", label: "多空辩论", sub: "多方 vs 空方研究员" },
  { key: "risk", label: "风险评估", sub: "激进 · 中性 · 保守分析师" },
  { key: "decision", label: "最终决策", sub: "组合经理综合判断" },
]

const ORDER = ["analysts", "debate", "risk", "decision", "complete"]

function stageIndex(stage: string) {
  return ORDER.indexOf(stage)
}

interface Props {
  stage: string
  status: string
}

export default function ProgressTimeline({ stage, status }: Props) {
  return (
    <div className="max-w-md mx-auto py-16 px-6">
      <div className="text-center mb-10">
        <div className="text-4xl mb-3">📊</div>
        <h2 className="text-xl font-bold text-white">分析进行中</h2>
        <p className="text-gray-400 text-sm mt-1">完成后可离开此页，稍后回来查看</p>
      </div>

      <div className="space-y-0">
        {STAGES.map((s, i) => {
          const done = stageIndex(stage) > i || status === "complete"
          const active = stage === s.key && status === "running"

          return (
            <div key={s.key} className="flex gap-4">
              <div className="flex flex-col items-center">
                <div
                  className={`w-3 h-3 rounded-full mt-1 shrink-0 transition-colors ${
                    done ? "bg-buy" : active ? "bg-accent animate-pulse" : "bg-border"
                  }`}
                />
                {i < STAGES.length - 1 && (
                  <div className={`w-px flex-1 my-1 ${done ? "bg-buy/40" : "bg-border"}`} />
                )}
              </div>
              <div className={`pb-6 ${done || active ? "text-white" : "text-gray-500"}`}>
                <div className="font-medium text-sm">{s.label}</div>
                <div className="text-xs opacity-60">{s.sub}</div>
              </div>
            </div>
          )
        })}
      </div>

      {status === "failed" && (
        <p className="text-red-400 text-center text-sm mt-4">分析失败，请重试</p>
      )}
    </div>
  )
}
