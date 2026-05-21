// web/src/pages/NewAnalysis.tsx
import { useState } from "react"
import { useNavigate } from "react-router-dom"
import { api } from "../api/client"

const ANALYSTS = [
  { key: "fundamentals", label: "基本面", emoji: "📊" },
  { key: "sentiment", label: "情绪", emoji: "💬" },
  { key: "news", label: "新闻", emoji: "📰" },
  { key: "market", label: "技术", emoji: "📈" },
]

const DEPTH = [
  { value: 1, label: "快速", desc: "约3分钟" },
  { value: 2, label: "标准", desc: "约7分钟" },
  { value: 3, label: "深度", desc: "约15分钟" },
]

export default function NewAnalysis() {
  const navigate = useNavigate()
  const [ticker, setTicker] = useState("")
  const [tradeDate, setTradeDate] = useState(new Date().toISOString().slice(0, 10))
  const [selectedAnalysts, setSelectedAnalysts] = useState<string[]>(ANALYSTS.map((a) => a.key))
  const [depth, setDepth] = useState(1)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState("")

  const toggleAnalyst = (key: string) => {
    setSelectedAnalysts((prev) =>
      prev.includes(key) ? prev.filter((k) => k !== key) : [...prev, key]
    )
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!ticker.trim()) return setError("请输入股票代码")
    if (selectedAnalysts.length === 0) return setError("至少选择一个分析师")
    setError("")
    setLoading(true)
    try {
      const analysis = await api.createAnalysis({
        ticker: ticker.trim().toUpperCase(),
        trade_date: tradeDate,
        analysts: selectedAnalysts,
        depth,
      })
      navigate(`/report/${analysis.id}`)
    } catch (err: any) {
      setError(err?.response?.data?.detail || "提交失败，请重试")
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="max-w-lg mx-auto px-6 py-10">
      <h1 className="text-2xl font-bold text-white mb-8">新建分析</h1>
      <form onSubmit={handleSubmit} className="space-y-6">
        <div>
          <label className="block text-sm text-gray-400 mb-1">股票代码</label>
          <input
            className="w-full bg-surface border border-border rounded-md px-3 py-2 text-white focus:outline-none focus:border-accent"
            placeholder="例如：600519.SS / 0700.HK / NVDA"
            value={ticker}
            onChange={(e) => setTicker(e.target.value)}
          />
          <p className="mt-1 text-xs text-gray-500">
            A股需加交易所后缀：沪市 <span className="text-gray-400">.SS</span>，深市 <span className="text-gray-400">.SZ</span>（如 <span className="text-gray-400">159992.SZ</span>）；港股加 <span className="text-gray-400">.HK</span>
          </p>
        </div>

        <div>
          <label className="block text-sm text-gray-400 mb-1">分析日期</label>
          <input
            type="date"
            className="w-full bg-surface border border-border rounded-md px-3 py-2 text-white focus:outline-none focus:border-accent"
            value={tradeDate}
            onChange={(e) => setTradeDate(e.target.value)}
          />
        </div>

        <div>
          <label className="block text-sm text-gray-400 mb-2">包含分析师</label>
          <div className="flex gap-2 flex-wrap">
            {ANALYSTS.map((a) => (
              <button
                key={a.key}
                type="button"
                onClick={() => toggleAnalyst(a.key)}
                className={`px-3 py-1.5 rounded-md text-sm border transition-colors ${
                  selectedAnalysts.includes(a.key)
                    ? "bg-accent/20 border-accent text-accent"
                    : "bg-surface border-border text-gray-400 hover:border-gray-500"
                }`}
              >
                {a.emoji} {a.label}
              </button>
            ))}
          </div>
        </div>

        <div>
          <label className="block text-sm text-gray-400 mb-2">研究深度</label>
          <div className="flex gap-2">
            {DEPTH.map((d) => (
              <button
                key={d.value}
                type="button"
                onClick={() => setDepth(d.value)}
                className={`flex-1 py-2 rounded-md text-sm border transition-colors ${
                  depth === d.value
                    ? "bg-accent/20 border-accent text-accent"
                    : "bg-surface border-border text-gray-400 hover:border-gray-500"
                }`}
              >
                <div className="font-medium">{d.label}</div>
                <div className="text-xs opacity-60">{d.desc}</div>
              </button>
            ))}
          </div>
        </div>

        {error && <p className="text-red-400 text-sm">{error}</p>}

        <button
          type="submit"
          disabled={loading}
          className="w-full bg-accent text-black font-bold py-2.5 rounded-md hover:bg-accent/80 disabled:opacity-50 transition-colors"
        >
          {loading ? "提交中…" : "开始分析 →"}
        </button>
      </form>
    </div>
  )
}
