// web/src/components/ReportBanner.tsx
interface Props {
  ticker: string
  tickerName: string | null
  tradeDate: string
  decision: string
  depth: number
  analystCount: number
}

const DECISION_STYLE: Record<string, string> = {
  BUY: "text-buy border-buy bg-buy/10",
  SELL: "text-sell border-sell bg-sell/10",
  HOLD: "text-hold border-hold bg-hold/10",
}

export default function ReportBanner({
  ticker,
  tickerName,
  tradeDate,
  decision,
  depth,
  analystCount,
}: Props) {
  return (
    <div className="sticky top-0 z-10 bg-surface/95 backdrop-blur border-b border-border px-6 py-3 flex items-center justify-between">
      <div>
        <div className="flex items-center gap-3">
          <span
            className={`text-lg font-bold px-3 py-0.5 rounded border ${
              DECISION_STYLE[decision] ?? "text-gray-400 border-border"
            }`}
          >
            {decision}
          </span>
          <span className="font-semibold text-white">{ticker}</span>
          {tickerName && <span className="text-gray-400 text-sm">{tickerName}</span>}
        </div>
        <div className="text-xs text-gray-400 mt-0.5">
          {tradeDate} · 研究深度 {depth} · {analystCount} 位分析师
        </div>
      </div>
      <button
        onClick={() => window.print()}
        className="text-sm text-gray-400 hover:text-accent border border-border rounded-md px-3 py-1 hover:border-accent transition-colors"
      >
        导出
      </button>
    </div>
  )
}
