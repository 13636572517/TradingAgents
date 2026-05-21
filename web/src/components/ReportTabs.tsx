// web/src/components/ReportTabs.tsx
import { useState } from "react"
import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"
import type { AnalysisResult } from "../types"

const TABS = [
  { key: "fundamentals_report",   label: "基本面", analyst: "fundamentals" },
  { key: "sentiment_report",      label: "情绪",   analyst: "sentiment" },
  { key: "news_report",           label: "新闻",   analyst: "news" },
  { key: "market_report",         label: "技术",   analyst: "market" },
  { key: "investment_plan",       label: "投研总结", analyst: null },
  { key: "trader_investment_plan", label: "交易建议", analyst: null },
  { key: "final_trade_decision",  label: "最终决策", analyst: null },
]

interface Props {
  result: AnalysisResult
  analysts: string[]
}

export default function ReportTabs({ result, analysts }: Props) {
  const availableTabs = TABS.filter((t) =>
    t.analyst ? analysts.includes(t.analyst) : true
  )

  const [active, setActive] = useState(availableTabs[0]?.key ?? "")
  const content = result[active as keyof AnalysisResult] ?? "*暂无内容*"

  return (
    <div>
      {/* Tab bar */}
      <div className="flex border-b border-border overflow-x-auto">
        {availableTabs.map((t) => (
          <button
            key={t.key}
            onClick={() => setActive(t.key)}
            className={`px-4 py-2.5 text-sm whitespace-nowrap border-b-2 transition-colors ${
              active === t.key
                ? "border-accent text-accent"
                : "border-transparent text-gray-400 hover:text-white"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* Content */}
      <div className="p-6 overflow-x-auto">
        <div className="report-content">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
        </div>
      </div>
    </div>
  )
}
