// web/src/pages/Screener.tsx
import { useEffect, useState, useCallback } from "react"
import { useNavigate } from "react-router-dom"
import { api } from "../api/client"
import type { ScreeningRun, ScreeningCandidate, BoardValuation } from "../types"

function fmtYi(v: number | null | undefined): string {
  if (v === null || v === undefined) return "—"
  return `${(v / 1e8).toFixed(1)}亿`
}

function fmtNum(v: number | null | undefined, suffix = ""): string {
  if (v === null || v === undefined) return "—"
  return `${v.toFixed(1)}${suffix}`
}

function fmtPct(v: number | null | undefined): string {
  if (v === null || v === undefined) return "—"
  return `${v.toFixed(0)}%`
}

// ── Board Card ────────────────────────────────────────────────────────────────

function BoardCard({
  board, candidates, onAnalyze, analyzingId,
}: {
  board: BoardValuation
  candidates: ScreeningCandidate[]
  onAnalyze: (c: ScreeningCandidate) => void
  analyzingId: string | null
}) {
  const [expanded, setExpanded] = useState(false)
  const pctClass = board.is_undervalued
    ? "border-amber-500/50 bg-amber-950/10 hover:bg-amber-950/20"
    : "border-border bg-surface hover:bg-white/[0.02]"

  return (
    <div
      className={`rounded-lg border overflow-hidden cursor-pointer transition-colors ${pctClass}`}
      onClick={() => setExpanded((v) => !v)}
    >
      {/* Card body */}
      <div className="px-3 py-2.5">
        <div className="flex items-center justify-between mb-1.5">
          <span className="font-medium text-gray-100 text-sm truncate">{board.name}</span>
          {board.is_undervalued && (
            <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-amber-500/20 text-amber-300 border border-amber-500/40 shrink-0 ml-1">
              低估
            </span>
          )}
        </div>
        <div className="flex items-center gap-x-3 gap-y-0.5 text-xs text-gray-500 flex-wrap">
          <span>PE {fmtNum(board.pe)}</span>
          <span>PB {fmtNum(board.pb)}</span>
          {board.pe_pct !== null && board.pb_pct !== null && (
            <>
              <span className={board.is_undervalued ? "text-buy" : ""}>
                PE分位 {fmtPct(board.pe_pct)}
              </span>
              <span className={board.is_undervalued ? "text-buy" : ""}>
                PB分位 {fmtPct(board.pb_pct)}
              </span>
            </>
          )}
          <span>{board.member_count ?? "—"} 只</span>
        </div>
      </div>

      {/* Expanded: candidate list */}
      {expanded && candidates.length > 0 && (
        <div className="border-t border-border divide-y divide-border" onClick={(e) => e.stopPropagation()}>
          {candidates.map((c) => (
            <div key={c.id} className="flex items-center gap-2 px-3 py-2">
              <span className="w-5 text-center text-[10px] text-gray-600">#{c.rank_in_board}</span>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-1.5">
                  <span className="font-medium text-gray-200 text-xs truncate">{c.ticker_name ?? c.ticker}</span>
                  <span className="text-[10px] text-gray-600">{c.ticker}</span>
                  {c.score !== null && (
                    <span className="text-[9px] px-1 py-px rounded bg-accent/10 text-accent shrink-0">
                      {c.score}
                    </span>
                  )}
                </div>
                <div className="text-[10px] text-gray-500 mt-0.5 flex gap-x-2">
                  <span>市值 {fmtYi(c.total_mktcap)}</span>
                  <span>PE {fmtNum(c.pe)}</span>
                  {c.roe !== null && <span>ROE {fmtNum(c.roe, "%")}</span>}
                </div>
              </div>
              <button
                onClick={(e) => { e.stopPropagation(); onAnalyze(c) }}
                disabled={analyzingId === c.id}
                className={`text-[10px] px-2 py-1 rounded-full shrink-0 transition-colors ${
                  c.analysis_id
                    ? "border border-accent/40 text-accent"
                    : "bg-accent/15 border border-accent text-accent"
                } disabled:opacity-50`}
              >
                {analyzingId === c.id ? "提交中" : c.analysis_id ? "查看" : "分析"}
              </button>
            </div>
          ))}
        </div>
      )}
      {expanded && candidates.length === 0 && (
        <div className="border-t border-border px-3 py-2 text-[10px] text-gray-600">
          暂无符合条件的候选股
        </div>
      )}
    </div>
  )
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function Screener() {
  const navigate = useNavigate()
  const [run, setRun] = useState<ScreeningRun | null>(null)
  const [loading, setLoading] = useState(true)
  const [starting, setStarting] = useState(false)
  const [autoAnalyze, setAutoAnalyze] = useState(false)
  const [depth, setDepth] = useState(1)
  const [analyzingId, setAnalyzingId] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [tab, setTab] = useState<"sw1" | "sw2">("sw1")

  const loadLatest = useCallback(async () => {
    try {
      const r = await api.getLatestScreeningRun()
      setRun(r)
    } catch {
      setRun(null)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { loadLatest() }, [loadLatest])

  // Poll while running
  useEffect(() => {
    if (!run || run.status !== "running") return
    const id = setInterval(async () => {
      try {
        const r = await api.getScreeningRun(run.id)
        setRun(r)
      } catch { /* ignore */ }
    }, 4000)
    return () => clearInterval(id)
  }, [run])

  const handleRun = async () => {
    setStarting(true)
    setError(null)
    try {
      const r = await api.runScreening({ auto_analyze: autoAnalyze, depth })
      setRun(r)
    } catch (e: any) {
      setError(e?.response?.data?.detail ?? "启动筛选失败")
    } finally {
      setStarting(false)
    }
  }

  const handleAnalyze = async (c: ScreeningCandidate) => {
    if (c.analysis_id) { navigate(`/report/${c.analysis_id}`); return }
    setAnalyzingId(c.id)
    try {
      const a = await api.analyzeCandidate(c.id, depth)
      navigate(`/report/${a.id}`)
    } catch (e: any) {
      setError(e?.response?.data?.detail ?? "分析启动失败")
    } finally {
      setAnalyzingId(null)
    }
  }

  // Data
  const allBoards: BoardValuation[] = run?.summary?.all_boards ?? []
  const candidates = run?.candidates ?? []

  // Filter by tab
  const level = tab === "sw1" ? 1 : 2
  const filteredBoards = allBoards.filter((b) => b.level === level)
  const filteredCandidates = candidates.filter((c) => c.board_level === level)

  // Sort: undervalued first, then by PE+PB percentile
  const sortedBoards = [...filteredBoards].sort((a, b) => {
    if (a.is_undervalued !== b.is_undervalued) return a.is_undervalued ? -1 : 1
    return ((a.pe_pct ?? 100) + (a.pb_pct ?? 100)) - ((b.pe_pct ?? 100) + (b.pb_pct ?? 100))
  })

  const sw1Count = run?.summary?.sw1_count ?? 0
  const sw2Count = run?.summary?.sw2_count ?? 0
  const sw1Uv = run?.summary?.sw1_undervalued ?? 0
  const sw2Uv = run?.summary?.sw2_undervalued ?? 0

  return (
    <div className="max-w-6xl mx-auto px-4 py-6">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-3 mb-5">
        <div>
          <h1 className="text-xl font-semibold text-gray-100">智能选股</h1>
          <p className="text-xs text-gray-500 mt-1">
            扫描申万行业板块估值分位，筛出被低估板块的龙头股
          </p>
        </div>
        <div className="flex items-center gap-3">
          <label className="flex items-center gap-1.5 text-xs text-gray-400 cursor-pointer">
            <input type="checkbox" checked={autoAnalyze}
              onChange={(e) => setAutoAnalyze(e.target.checked)} className="accent-accent" />
            自动分析Top3
          </label>
          <select value={depth} onChange={(e) => setDepth(Number(e.target.value))}
            className="bg-surface border border-border rounded px-2 py-1.5 text-xs text-gray-300">
            <option value={1}>快速</option>
            <option value={2}>标准</option>
            <option value={3}>深度</option>
          </select>
          <button onClick={handleRun} disabled={starting || run?.status === "running"}
            className="text-sm px-4 py-1.5 rounded-full bg-accent/15 border border-accent text-accent hover:bg-accent/25 transition-colors disabled:opacity-50">
            {starting || run?.status === "running" ? "筛选中…" : "立即筛选"}
          </button>
        </div>
      </div>

      {error && (
        <div className="mb-4 px-3 py-2 rounded bg-red-500/10 border border-red-500/40 text-red-300 text-sm">
          {error}
        </div>
      )}

      {loading && <p className="text-gray-500 text-sm">加载中…</p>}

      {!loading && !run && (
        <div className="text-center py-16 text-gray-500">
          <p className="text-3xl mb-3">🔍</p>
          <p className="text-sm">还没有筛选记录，点击右上角「立即筛选」开始。</p>
        </div>
      )}

      {run && (
        <>
          {/* Run meta */}
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-gray-500 mb-4">
            <span>日期 {run.run_date}</span>
            {run.summary?.boards_scanned !== undefined && (
              <span>共扫描 {run.summary.boards_scanned} 个板块</span>
            )}
            {sw1Uv > 0 && <span className="text-amber-300">SW1 低估 {sw1Uv}/{sw1Count}</span>}
            {sw2Uv > 0 && <span className="text-amber-300">SW2 低估 {sw2Uv}/{sw2Count}</span>}
            {run.summary?.candidate_count !== undefined && (
              <span>候选 {run.summary.candidate_count} 只</span>
            )}
          </div>

          {run.status === "running" && (
            <div className="px-3 py-2 rounded bg-accent/10 border border-accent/30 text-accent text-sm mb-4">
              {run.error || "正在扫描全市场板块与成分股，约需 1-3 分钟，请稍候…"}
            </div>
          )}
          {run.status === "failed" && (
            <div className="px-3 py-2 rounded bg-red-500/10 border border-red-500/40 text-red-300 text-sm mb-4">
              筛选失败：{run.error}
            </div>
          )}

          {run.status === "complete" && (
            <>
              {/* Tabs */}
              <div className="flex gap-1 mb-4 border-b border-border">
                <button
                  onClick={() => setTab("sw1")}
                  className={`px-4 py-2 text-sm transition-colors border-b-2 ${
                    tab === "sw1"
                      ? "border-accent text-accent font-medium"
                      : "border-transparent text-gray-500 hover:text-gray-300"
                  }`}
                >
                  申万一级（{sw1Count} 个行业）
                  {sw1Uv > 0 && (
                    <span className="ml-1.5 text-[10px] px-1.5 py-0.5 rounded-full bg-amber-500/20 text-amber-300">
                      {sw1Uv} 低估
                    </span>
                  )}
                </button>
                <button
                  onClick={() => setTab("sw2")}
                  className={`px-4 py-2 text-sm transition-colors border-b-2 ${
                    tab === "sw2"
                      ? "border-accent text-accent font-medium"
                      : "border-transparent text-gray-500 hover:text-gray-300"
                  }`}
                >
                  申万二级（{sw2Count} 个子行业）
                  {sw2Uv > 0 && (
                    <span className="ml-1.5 text-[10px] px-1.5 py-0.5 rounded-full bg-amber-500/20 text-amber-300">
                      {sw2Uv} 低估
                    </span>
                  )}
                </button>
              </div>

              {/* Board cards grid */}
              {sortedBoards.length === 0 && (
                <p className="text-gray-500 text-sm py-8 text-center">该分类下暂无板块数据。</p>
              )}
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
                {sortedBoards.map((board) => (
                  <BoardCard
                    key={`${tab}:${board.name}`}
                    board={board}
                    candidates={filteredCandidates
                      .filter((c) => c.board_name === board.name)
                      .sort((a, b2) => (a.rank_in_board ?? 99) - (b2.rank_in_board ?? 99))
                    }
                    onAnalyze={handleAnalyze}
                    analyzingId={analyzingId}
                  />
                ))}
              </div>
            </>
          )}
        </>
      )}
    </div>
  )
}
