// web/src/components/UsageCard.tsx
import type { UsageStats } from "../types"

function fmt(n: number) {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(2)}M`
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`
  return String(n)
}

function Row({ label, slot }: { label: string; slot: UsageStats["quick"] }) {
  const totalTokens = slot.tokens_in + slot.tokens_out
  return (
    <div className="flex items-center gap-3 text-sm">
      <span className="text-gray-500 w-20 shrink-0">{label}</span>
      <span className="text-gray-300 w-10 text-right">{slot.calls}次</span>
      <span className="text-gray-500 mx-1">|</span>
      <span className="text-gray-400 text-xs flex-1">
        ↑{fmt(slot.tokens_in)} ↓{fmt(slot.tokens_out)}
      </span>
      {slot.tool_calls > 0 && (
        <>
          <span className="text-gray-500 mx-1">|</span>
          <span className="text-gray-500 text-xs">工具 {slot.tool_calls}次</span>
        </>
      )}
    </div>
  )
}

export default function UsageCard({ usage }: { usage: UsageStats }) {
  const totalTokens = (
    usage.quick.tokens_in + usage.quick.tokens_out +
    usage.deep.tokens_in  + usage.deep.tokens_out
  )
  const hasCost = usage.total_cost_cny > 0

  return (
    <div className="border-t border-border mt-4 pt-4 px-6 pb-4">
      <div className="text-xs text-gray-500 uppercase tracking-wide mb-3">本次用量</div>
      <div className="bg-surface rounded-lg border border-border p-3 space-y-2">
        <Row label="快速模型" slot={usage.quick} />
        <Row label="深度模型" slot={usage.deep} />
        
        {/* Token summary row */}
        <div className="flex items-center justify-between text-xs pt-1">
          <span className="text-gray-500 w-20">Token 用量</span>
          <div className="flex items-center gap-8">
            <span className="text-gray-400 font-mono w-20 text-right">
              {usage.quick.tokens_in + usage.quick.tokens_out > 0 ? fmt(usage.quick.tokens_in + usage.quick.tokens_out) : "-"}
            </span>
            <span className="text-gray-400 font-mono w-20 text-right">
              {usage.deep.tokens_in + usage.deep.tokens_out > 0 ? fmt(usage.deep.tokens_in + usage.deep.tokens_out) : "-"}
            </span>
          </div>
        </div>
        
        {/* Cost summary row */}
        <div className="flex items-center justify-between text-xs">
          <span className="text-gray-500 w-20">费用估算</span>
          <div className="flex items-center gap-8">
            <span className="font-mono w-20 text-right">
              {usage.quick.cost_cny > 0 ? `¥${usage.quick.cost_cny.toFixed(4)}` : "-"}
            </span>
            <span className="font-mono w-20 text-right">
              {usage.deep.cost_cny > 0 ? `¥${usage.deep.cost_cny.toFixed(4)}` : "-"}
            </span>
          </div>
        </div>
        
        {/* Total row */}
        <div className="border-t border-border pt-2 flex items-center justify-between text-sm">
          <span className="text-gray-500">合计</span>
          <div className="flex items-center gap-8">
            <span className={`font-mono ${hasCost ? "text-accent font-semibold" : "text-gray-500"}`}>
              {hasCost ? `¥${usage.total_cost_cny.toFixed(4)}` : "-"}
            </span>
            <span className="text-white font-semibold font-mono">
              {totalTokens > 0 ? fmt(totalTokens) : "-"}
            </span>
          </div>
        </div>
        
        <div className="text-xs text-gray-600">
          快速：{usage.quick.model} &nbsp;·&nbsp; 深度：{usage.deep.model}
        </div>
      </div>
    </div>
  )
}
