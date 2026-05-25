// web/src/pages/StatsPage.tsx
import { useEffect, useState } from "react"
import { api } from "../api/client"
import type { AggregateStats } from "../types"

function fmt(n: number) {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(2)}M`
  if (n >= 1_000)     return `${(n / 1_000).toFixed(1)}k`
  return String(n)
}

function StatBox({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="bg-surface border border-border rounded-xl p-4">
      <div className="text-gray-500 text-xs mb-1">{label}</div>
      <div className="text-white text-2xl font-bold">{value}</div>
      {sub && <div className="text-gray-500 text-xs mt-1">{sub}</div>}
    </div>
  )
}

function ModelRow({
  role, slot,
}: {
  role: string
  slot: AggregateStats["quick"]
}) {
  const totalTokens = slot.tokens_in + slot.tokens_out
  return (
    <div className="bg-surface border border-border rounded-xl p-4 space-y-3">
      <div className="flex items-center justify-between">
        <div>
          <span className="text-white font-semibold">{role === "quick" ? "快速模型" : "深度模型"}</span>
          <span className="ml-2 text-gray-500 text-xs">{slot.model}</span>
        </div>
        <span className="flex items-center gap-2">
          {slot.cost_cny > 0 && (
            <span className="text-accent font-mono font-bold text-sm">¥{slot.cost_cny.toFixed(4)}</span>
          )}
          <span className="text-white font-mono font-bold">
            {totalTokens > 0 ? fmt(totalTokens) : "-"}
          </span>
        </span>
      </div>
      <div className="grid grid-cols-3 gap-3 text-sm">
        <div>
          <div className="text-gray-500 text-xs">LLM 调用</div>
          <div className="text-white font-semibold">{slot.calls.toLocaleString()}</div>
        </div>
        <div>
          <div className="text-gray-500 text-xs">Token 消耗</div>
          <div className="text-white font-semibold">{fmt(totalTokens)}</div>
          <div className="text-gray-600 text-xs">↑{fmt(slot.tokens_in)} ↓{fmt(slot.tokens_out)}</div>
        </div>
        <div>
          <div className="text-gray-500 text-xs">工具调用</div>
          <div className="text-white font-semibold">{slot.tool_calls.toLocaleString()}</div>
        </div>
      </div>
      {/* Token bar */}
      {totalTokens > 0 && (
        <div className="h-1.5 bg-bg rounded-full overflow-hidden flex">
          <div
            className="bg-accent h-full"
            style={{ width: `${(slot.tokens_in / totalTokens) * 100}%` }}
          />
          <div
            className="bg-accent/40 h-full"
            style={{ width: `${(slot.tokens_out / totalTokens) * 100}%` }}
          />
        </div>
      )}
      <div className="flex gap-3 text-xs text-gray-600">
        <span className="flex items-center gap-1">
          <span className="w-2 h-2 rounded-full bg-accent inline-block" />输入
        </span>
        <span className="flex items-center gap-1">
          <span className="w-2 h-2 rounded-full bg-accent/40 inline-block" />输出
        </span>
      </div>
    </div>
  )
}

export default function StatsPage() {
  const [stats, setStats] = useState<AggregateStats | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api.getAggregateStats().then((s) => {
      setStats(s)
      setLoading(false)
    })
  }, [])

  if (loading) return <div className="p-10 text-gray-400">加载中…</div>
  if (!stats)  return <div className="p-10 text-red-400">加载失败</div>

  const totalTokens = (
    stats.quick.tokens_in + stats.quick.tokens_out +
    stats.deep.tokens_in  + stats.deep.tokens_out
  )

  // Sort daily data
  const days = Object.entries(stats.by_date)
    .sort(([a], [b]) => a.localeCompare(b))
    .slice(-14)  // last 14 days

  const maxTokens = Math.max(...days.map(([, d]) => d.tokens), 0.0001)

  return (
    <div className="px-6 py-8 max-w-3xl mx-auto">
      <h1 className="text-2xl font-bold text-white mb-6">用量统计</h1>

      {/* Summary boxes */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3 mb-6">
        <StatBox label="累计分析" value={String(stats.total_analyses)} sub={`${stats.completed_analyses} 次完成`} />
        <StatBox label="总 Token" value={fmt(totalTokens)} sub="输入 + 输出" />
        <StatBox label="总 LLM 调用" value={String(stats.quick.calls + stats.deep.calls)} />
        <StatBox label="总工具调用" value={String(stats.quick.tool_calls + stats.deep.tool_calls)} />
        {stats.total_cost_cny > 0 && (
          <StatBox label="总费用" value={`¥${stats.total_cost_cny.toFixed(3)}`} sub="估算值" />
        )}
      </div>

      {/* Per-model breakdown */}
      {stats.completed_analyses > 0 ? (
        <>
          <h2 className="text-gray-400 text-xs uppercase tracking-wide mb-3">模型明细</h2>
          <div className="grid md:grid-cols-2 gap-3 mb-6">
            <ModelRow role="quick" slot={stats.quick} />
            <ModelRow role="deep"  slot={stats.deep} />
          </div>

          {/* Daily token chart */}
          {days.length > 0 && (
            <>
              <h2 className="text-gray-400 text-xs uppercase tracking-wide mb-3">每日 Token 用量（近14天）</h2>
              <div className="bg-surface border border-border rounded-xl p-4">
                <div className="flex items-end gap-1.5 h-28">
                  {days.map(([date, d]) => (
                    <div key={date} className="flex-1 flex flex-col items-center gap-1 group">
                      <div className="text-xs text-gray-500 opacity-0 group-hover:opacity-100 transition-opacity whitespace-nowrap">
                        {fmt(d.tokens)}
                      </div>
                      <div
                        className="w-full bg-accent/60 hover:bg-accent rounded-sm transition-colors min-h-[2px]"
                        style={{ height: `${Math.max(2, (d.tokens / maxTokens) * 80)}px` }}
                      />
                      <div className="text-gray-600 text-[10px] rotate-45 origin-left whitespace-nowrap">
                        {date.slice(5)}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </>
          )}
        </>
      ) : (
        <div className="text-center text-gray-500 py-12">
          <p className="text-lg mb-1">暂无完成的分析</p>
          <p className="text-sm">完成一次分析后，用量数据将在这里显示</p>
        </div>
      )}

      <p className="text-gray-600 text-xs mt-6">
        * 费用基于配置的每百万 Token 价格计算（可在 API 配置页面修改）。实际费用请以服务商账单为准。
      </p>
    </div>
  )
}
