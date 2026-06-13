// web/src/pages/BoardDetail.tsx
import { useEffect, useMemo, useState } from "react"
import { useNavigate, useParams } from "react-router-dom"
import { api } from "../api/client"
import type { BoardMember } from "../types"

type SortKey = "rank" | "mktcap" | "pe" | "pb" | "roe" | "pct_change"

function fmtNum(v: number | null | undefined, digits = 2, suffix = ""): string {
  if (v === null || v === undefined) return "—"
  return `${v.toFixed(digits)}${suffix}`
}
function fmtYi(v: number | null | undefined): string {
  if (v === null || v === undefined) return "—"
  return `${(v / 1e8).toFixed(1)}亿`
}
function pctClass(v: number | null | undefined): string {
  if (v === null || v === undefined || v === 0) return "text-gray-400"
  return v > 0 ? "text-red-400" : "text-green-400"
}

export default function BoardDetail() {
  const { runId = "", level = "1", name = "" } = useParams()
  const boardName = decodeURIComponent(name)
  const navigate = useNavigate()

  const [members, setMembers] = useState<BoardMember[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [analyzingTicker, setAnalyzingTicker] = useState<string | null>(null)
  const [sortKey, setSortKey] = useState<SortKey>("rank")
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc")
  const [showCandidatesOnly, setShowCandidatesOnly] = useState(false)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    api.getBoardMembers(runId, Number(level), boardName)
      .then((r) => {
        if (!cancelled) setMembers(r.members)
      })
      .catch((e) => {
        if (!cancelled) setError(e?.response?.data?.detail ?? "加载失败")
      })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [runId, level, boardName])

  const sorted = useMemo(() => {
    const arr = showCandidatesOnly ? members.filter((m) => m.is_candidate) : [...members]
    const getter: Record<SortKey, (m: BoardMember) => number> = {
      rank: (m) => m.is_candidate
        ? (m.rank_in_board ?? 999)
        : 1000 + (-(m.total_mktcap ?? 0) / 1e8),
      mktcap: (m) => m.total_mktcap ?? 0,
      pe: (m) => m.pe ?? Infinity,
      pb: (m) => m.pb ?? Infinity,
      roe: (m) => m.roe ?? -Infinity,
      pct_change: (m) => m.pct_change ?? 0,
    }
    const g = getter[sortKey]
    arr.sort((a, b) => {
      const d = g(a) - g(b)
      return sortDir === "asc" ? d : -d
    })
    return arr
  }, [members, sortKey, sortDir, showCandidatesOnly])

  const toggleSort = (key: SortKey, defaultDir: "asc" | "desc" = "asc") => {
    if (sortKey === key) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"))
    } else {
      setSortKey(key)
      setSortDir(defaultDir)
    }
  }

  const handleAnalyze = async (m: BoardMember) => {
    if (m.analysis_id) { navigate(`/report/${m.analysis_id}`); return }
    setAnalyzingTicker(m.ticker)
    try {
      if (m.candidate_id) {
        const a = await api.analyzeCandidate(m.candidate_id, 1)
        navigate(`/report/${a.id}`)
      } else {
        const a = await api.createAnalysis({
          ticker: m.ticker,
          trade_date: new Date().toISOString().slice(0, 10),
          analysts: ["fundamentals", "sentiment", "news", "market"],
          depth: 1,
        })
        navigate(`/report/${a.id}`)
      }
    } catch (e: any) {
      setError(e?.response?.data?.detail ?? "分析启动失败")
    } finally {
      setAnalyzingTicker(null)
    }
  }

  const Caret = ({ k }: { k: SortKey }) => (
    sortKey === k ? <span className="ml-0.5 text-[9px]">{sortDir === "asc" ? "▲" : "▼"}</span> : null
  )

  const candidateCount = members.filter((m) => m.is_candidate).length

  return (
    <div className="max-w-6xl mx-auto px-4 py-6">
      <button
        onClick={() => navigate(-1)}
        className="text-xs text-gray-500 hover:text-gray-300 mb-3"
      >
        ← 返回筛选结果
      </button>

      <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
        <div>
          <h1 className="text-xl font-semibold text-gray-100">
            {boardName} <span className="text-xs text-gray-500 font-normal ml-2">SW{level}</span>
          </h1>
          <p className="text-xs text-gray-500 mt-1">
            共 {members.length} 只成分股 · 已入选候选 {candidateCount} 只
          </p>
        </div>
        <label className="flex items-center gap-1.5 text-xs text-gray-400 cursor-pointer">
          <input
            type="checkbox"
            checked={showCandidatesOnly}
            onChange={(e) => setShowCandidatesOnly(e.target.checked)}
            className="accent-accent"
          />
          仅显示候选
        </label>
      </div>

      {error && (
        <div className="mb-3 text-xs text-red-400 bg-red-950/30 border border-red-900/50 rounded px-3 py-2">
          {error}
        </div>
      )}

      {loading ? (
        <div className="text-center py-12 text-sm text-gray-500">加载成分股中…</div>
      ) : sorted.length === 0 ? (
        <div className="text-center py-12 text-sm text-gray-500">暂无数据</div>
      ) : (
        <div className="overflow-x-auto rounded border border-border bg-surface">
          <table className="w-full text-xs">
            <thead className="bg-surface-2 text-gray-400">
              <tr>
                <th className="px-2 py-2 text-left font-medium cursor-pointer hover:text-gray-200"
                    onClick={() => toggleSort("rank")}>序<Caret k="rank" /></th>
                <th className="px-2 py-2 text-left font-medium">代码 / 名称</th>
                <th className="px-2 py-2 text-right font-medium">现价</th>
                <th className="px-2 py-2 text-right font-medium cursor-pointer hover:text-gray-200"
                    onClick={() => toggleSort("pct_change", "desc")}>涨跌<Caret k="pct_change" /></th>
                <th className="px-2 py-2 text-right font-medium cursor-pointer hover:text-gray-200"
                    onClick={() => toggleSort("mktcap", "desc")}>市值<Caret k="mktcap" /></th>
                <th className="px-2 py-2 text-right font-medium cursor-pointer hover:text-gray-200"
                    onClick={() => toggleSort("pe")}>PE<Caret k="pe" /></th>
                <th className="px-2 py-2 text-right font-medium cursor-pointer hover:text-gray-200"
                    onClick={() => toggleSort("pb")}>PB<Caret k="pb" /></th>
                <th className="px-2 py-2 text-right font-medium cursor-pointer hover:text-gray-200"
                    onClick={() => toggleSort("roe", "desc")}>ROE<Caret k="roe" /></th>
                <th className="px-2 py-2 text-center font-medium">操作</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {sorted.map((m) => (
                <tr
                  key={m.code}
                  className={m.is_candidate ? "bg-accent/5" : "hover:bg-surface-2/50"}
                >
                  <td className="px-2 py-2 text-gray-500">
                    {m.is_candidate ? (
                      <span className="inline-flex items-center gap-1">
                        <span className="text-[9px] px-1 rounded bg-accent/20 text-accent">候选</span>
                        {m.rank_in_board && <span>#{m.rank_in_board}</span>}
                      </span>
                    ) : (
                      <span className="text-gray-700">·</span>
                    )}
                  </td>
                  <td className="px-2 py-2">
                    <div className="flex flex-col">
                      <span className="font-mono text-gray-400">{m.code}</span>
                      <span className="text-gray-200 truncate max-w-[160px]">{m.name || "—"}</span>
                    </div>
                  </td>
                  <td className="px-2 py-2 text-right text-gray-200">{fmtNum(m.price, 2)}</td>
                  <td className={`px-2 py-2 text-right ${pctClass(m.pct_change)}`}>
                    {m.pct_change !== null && m.pct_change !== undefined
                      ? `${m.pct_change > 0 ? "+" : ""}${m.pct_change.toFixed(2)}%`
                      : "—"}
                  </td>
                  <td className="px-2 py-2 text-right text-gray-300">{fmtYi(m.total_mktcap)}</td>
                  <td className="px-2 py-2 text-right text-gray-300">{fmtNum(m.pe, 2)}</td>
                  <td className="px-2 py-2 text-right text-gray-300">{fmtNum(m.pb, 2)}</td>
                  <td className="px-2 py-2 text-right text-gray-300">
                    {m.roe !== null && m.roe !== undefined ? `${(m.roe * 100).toFixed(1)}%` : "—"}
                  </td>
                  <td className="px-2 py-2 text-center">
                    <button
                      onClick={() => handleAnalyze(m)}
                      disabled={analyzingTicker === m.ticker}
                      className="text-[10px] px-2 py-0.5 rounded bg-accent/20 text-accent hover:bg-accent/30 disabled:opacity-50"
                    >
                      {analyzingTicker === m.ticker ? "提交中" : m.analysis_id ? "查看" : "分析"}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
