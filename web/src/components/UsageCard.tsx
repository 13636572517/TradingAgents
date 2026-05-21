// web/src/components/UsageCard.tsx
import type { UsageStats } from "../types"

function fmt(n: number) {
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k`
  return String(n)
}

function Row({ label, slot }: { label: string; slot: UsageStats["quick"] }) {
  return (
    <div className="flex items-center gap-3 text-sm">
      <span className="text-gray-500 w-20 shrink-0">{label}</span>
      <span className="text-gray-300 w-10 text-right">{slot.calls}次</span>
      <span className="text-gray-500 mx-1">|</span>
      <span className="text-gray-400 text-xs">
        ↑{fmt(slot.tokens_in)} ↓{fmt(slot.tokens_out)} tokens
      </span>
      {slot.tool_calls > 0 && (
        <>
          <span className="text-gray-500 mx-1">|</span>
          <span className="text-gray-500 text-xs">工具 {slot.tool_calls}次</span>
        </>
      )}
      <span className="ml-auto text-gray-400 font-mono text-xs">
        {slot.cost_cny > 0 ? `¥${slot.cost_cny.toFixed(4)}` : "-"}
      </span>
    </div>
  )
}

export default function UsageCard({ usage }: { usage: UsageStats }) {
  return (
    <div className="border-t border-border mt-4 pt-4 px-6 pb-4">
      <div className="text-xs text-gray-500 uppercase tracking-wide mb-3">本次用量</div>
      <div className="bg-surface rounded-lg border border-border p-3 space-y-2">
        <Row label="快速模型" slot={usage.quick} />
        <Row label="深度模型" slot={usage.deep} />
        <div className="border-t border-border pt-2 flex justify-between text-sm">
          <span className="text-gray-500">合计</span>
          <span className="text-white font-semibold">
            {usage.total_cost_cny > 0
              ? `¥${usage.total_cost_cny.toFixed(4)}`
              : "未知（模型不在价格表中）"}
          </span>
        </div>
        <div className="text-xs text-gray-600">
          快速: {usage.quick.model} &nbsp;·&nbsp; 深度: {usage.deep.model}
        </div>
      </div>
    </div>
  )
}
